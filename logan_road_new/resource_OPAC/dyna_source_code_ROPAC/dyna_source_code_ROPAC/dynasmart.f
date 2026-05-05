      subroutine dynasmart(maxintervals)
! --
      use muc_mod

      integer starttime,endtime,error
      integer maxintervals
      integer dy_muc
      dy_muc = 0
! --
! -- Initialization 
! --
C	print *, 'Alex100'	
      call init
! --
C	print *, 'Alex200'
      call input()
C	print *, 'Alex300'
! -- number of assignment intervals

      allocate(past_phase(noofnodes*nu_mv),stat=error)
      if(error.ne.0) then
      write(911,*)'allcoate past_phase error-insufficient memory'
      stop
      endif
      past_phase(:)=0	

!      soint = nint((stagelength/tii)/tad)
      soint = nint((stagelength/tii)/tad)+1

! -- number of aggregation interavls
!      aggint = nint((stagelength/tii)/ftr)
      aggint = nint((stagelength/tii)/ftr)+1

 	  iti_nu = 1

!      if(iteration.eq.0.and.(realdm.ne.2.or.noofstops.gt.1.or.classpro(4)-classpro(3).gt.0.001.or.vms_num.gt.0)) then
      if((iteration.eq.0.and.(realdm.ne.2.or.noofstops.gt.1)).or.
     + ienroute_ok.eq.1.or.vms_num.gt.0) then

		if(realdm.ne.1) then
		call read_vehicles_check_hov()
		endif

        call allocate_ksp(dy_muc)
      endif

! -- print output file headers      
! --
      call title()   
! --      
! -- print out static network information.
! --
      write(666,*) ' '
      write(666,*) '****************************************'
      write(666,*) '*      Basic Information               *'
      write(666,*) '****************************************'
      write(666,*)
      write(666,*) 'NETWORK DATA '
      write(666,*) '------------ '
      write(666,'( "    Number of Nodes   : ",i7)') noofnodes_org
      write(666,'( "    Number of Links   : ",i7)') noofarcs_org
      write(666,'( "    Number of Zones   : ",i7)') nzones
      write(666,*) '***************************************'
      write(666,*)
      write(666,*) 'INTERSECTION CONTROL DATA'
      write(666,*) '-------------------------'
      nodetmp(:)=0

      do i=1,noofnodes
         do j=1,nu_control
           if(node(i,2).eq.j) nodetmp(j)=nodetmp(j)+1
         end do
      end do
! --
      write(666,'( "Number of No Control       : ",i7)') nodetmp(1)
      write(666,'( "Number of Yield Signs      : ",i7)') nodetmp(2)
      write(666,'( "Number of 4-Way Stop Signs : ",i7)') nodetmp(3)
      write(666,'( "Number of 2-Way Stop Signs : ",i7)') nodetmp(6)
      write(666,'( "Number of Pretimed Control : ",i7)') nodetmp(4)
      write(666,'( "Number of Actuated Control : ",i7)') nodetmp(5)
      write(666,*) '***************************************'
      write(666,*)
      write(666,*) 'RAMP DATA '
      write(666,*) '---------'
      write(666,'( "    Number of Metered Ramps : ",i7)') dec_num


	  !**************** start of addition ******************* 
	  if(dec_num.gt.0) then
	  do ir=1,dec_num
	  write(666,*)
	write(666,'("Ramp Meter No.        ",i3)') ir
	write(666,'("Metering Start Time   ",f7.3)') ramp_start(ir) 	
	write(666,'("Metering End Time     ",f7.3)') ramp_end(ir)
	write(666,'("Ramp Link             ",i7,"   -->",i7)') 
     +  detector(ir,6),detector(ir,7)
	write(666,'("Freeway Detector Link ",i7,"   -->",i7)') 
     +  detector(ir,2),detector(ir,3)
	write(666,'("Alpha                 ",f7.3)') ramp_par(ir,1)
	write(666,'("Beta                  ",f7.3)') ramp_par(ir,2)	
	write(666,'("Saturation Flow Rate  ",f10.3,"  veh/hr/ln")') 
     +  3600.0*ramp_par(ir,3)

	  enddo
	  endif
	  !**************** End of addition *******************	
	  
	  !write(666,'( "    Number of VMS Control                    : ",i7)') vms_num
      write(666,*) '***************************************'
      write(666,*)
      write(666,*) 'SOLUTION MODE '
      write(666,*) '-------------'
      if(itedex.eq.0) then
        write(666,*) '  Execute One-Shot Simulation Mode'
	  else
      write(666,*)'Execute Iterative Consistency Algorithm(Equlilbrium)'
      write(666,'( "Max. Number of Iterations  : ",i7)') itedex
      write(666,'( "Current Iteration          : ",i7)') iteration
	  endif
      write(666,*) '***************************************'
      write(666,*)
      write(666,*) 'TIME PERIODS '
      write(666,*) '------------'
      write(666,'("Planning Horizon(min)     : ",f9.1)') stagelength 
      write(666,'("Aggregation Interval(# of Sim Int)   : ",i7)') ftr
      write(666,'("Assignment Interval(# of Sim Int)    : ",i7)') tad
      write(666,'("Max # of Iterations               : ",i7)') itedex
      write(666,'("MUC Threshold (# of Vehicles) : ",f9.1)') muc_diff
      write(666,'("Convergence Threshold(# of Violation):",i7)') no_via
      write(666,*) '***************************************'
      write(666,*)
      write(666,*) 'CONGESTION PRICING '
      write(666,*) '------------------'
      write(666,'("Cost on Regular Links($)    : ",f9.1)') price_regular_c
      write(666,'("Cost of LOV on HOT Links($) : ",f9.1)') price_hot_lov_c
      write(666,'("Cost of HOV on HOT Links($) : ",f9.1)') price_hot_hov_c
      write(666,'("Value of Time($/hr)         : ",f9.1)') time_value
      write(666,*) '***************************************'
      write(666,*)
      write(666,*) 'TRAFFIC MANAGEMENT STRATEGIES '
      write(666,*) '-----------------------------'
	  if(vms_num.gt.0) then
      write(666,'("Number of Activated Dynamic Message Signs: 
     + ",i4)') vms_num
	  do iv = 1, vms_num
	  if(vmstype(iv).eq.1) then
      write(666,*) 
	write(666,'( "VMS # ",i3," Type:  Speed Advisory")') iv
  	write(666,'( " Location",i5," --",i5," From min ",f5.1," 
     +  To min ",f5.1)') nodenum(iunod(vms(iv,1))),nodenum(idnod
     +  (vms(iv,1))),vms_start(iv),vms_end(iv)
  	write(666,'("Speed Threshold ",f5.1," mph. Speed Adjustment 
     +  Percentage:",f5.1," %")') float(vms(iv,2)),float(vms(iv,3))
	  elseif(vmstype(iv).eq.2) then
      write(666,*)
	write(666,'( " VMS # ",i3,"  Type:  Route Advisory")') iv
  	  write(666,'( "  Location",i5," --",i5," From min ",f5.1,
     +  " To min ",f5.1)') nodenum(iunod(vms(iv,1))),nodenum(idnod
     +  (vms(iv,1))),vms_start(iv),vms_end(iv)	 
	  if(vms(iv,3).eq.0) then
	write(666,'("Diversion Applies for All Vehicles. 
     +  The",i3,"th Path is Chosen")') vms(iv,2)
	  else
	write(666,'("Diversion Applies for Vehilces Heading Zone 
     +  Number",i4,"The",i3,"th Path is Chosen")')vms(iv,3),vms(iv,2)
	  endif
	  elseif(vmstype(iv).eq.3) then
	  write(666,*)
      write(666,'("VMS # ",i3," Type: Congestion Warning")') iv
  	write(666,'("Location",i5,"--",i5," From min ",f5.1," 
     +  To min ",f5.1)') nodenum(iunod(vms(iv,1))),nodenum(idnod
     +  (vms(iv,1))),vms_start(iv),vms_end(iv)     
      if(vms(iv,3).eq.1) then
      write(666,'("The Best Path is Assigned to Responded Vehicles")')
	  else
      write(666,'("Random Paths Are Assigned to Responded Vehicles")')
	  endif
      write(666,'(i5,"% of Out-of-Vehicle Responsive Vehicles
     + Respond to VMS")') vms(iv,2)
	  endif
	  enddo
	  else
	write(666,'("No Traffic Management Strategy Was Specified")')
	  endif

      write(666,*) '***************************************'
      write(666,*)
      write(666,*) 'CAPACITY REDUCTION '
      write(666,*) '------------------ '
	  if(inci_num.gt.0) then
       write(666,*) '   -- Incident  --'
       do ic = 1, inci_num
  	write(666,'("Location",i5,"--",i5," From min ",f5.1," To min 
     +  ",f5.1,",  ",f5.1," % Capacity Reduction")') nodenum(iunod
     +  (incil(ic))),nodenum(idnod(incil(ic))),inci(ic,1),
     +  inci(ic,2),inci(ic,3)*100
	   enddo
	  endif
	  if(WorkZoneNum.gt.0) then
       write(666,*) '   -- Work Zone --'
       do ic = 1, WorkZoneNum
  	write(666,'("Location",i5," --",i5," From min ",f5.1," 
     +  To min ",f5.1,",  ",f5.1," % Capacity Reduction")') 
     +  nodenum(WorkZone(ic)%FNode),nodenum(WorkZone(ic)%TNode),
     +  WorkZone(ic)%ST,WorkZone(ic)%ET,WorkZone(ic)%CapRed*100.0

	   enddo
	  endif
	  if(inci_num.eq.0.and.WorkZoneNum.eq.0)then
       write(666,'("No Capacity Reduction Scenario Was Specified")')
	  endif

! --
! --  read_vehicles subroutine reads the veh. and path files. 
! --
! --
      write(6,*) ' Loading Information '
      write(6,*) '---------------------'
      write(6,*)
	  if(itedex.gt.0) write(6,*) 'Iteration', iteration
	  write(6,*) 
! --
      write(666,*)
      write(666,*) '****************************************'
      write(666,*) '*      Loading Information             *'
      write(666,*) '****************************************'
      write(666,*) 

! --
! -- get the initial K-shortest paths
! --
! --  chiu: the Iti_nu used in ksp_main and other ksp related
! --  sub are treated as variable as defined in init as 
! --  stagelength (min)
!      class4=classpro(4)-classpro(3)
!      if(iteration.eq.0.and.(realdm.ne.2.or.class4.gt.0.001.or.noofstops.gt.1.or.vms_num.gt.0)) then
c	print *, 'Alex345'

      if((iteration.eq.0.and.(realdm.ne.2.or.noofstops.gt.1))
     + .or.ienroute_ok.eq.1.or.vms_num.gt.0) then
!      Add movement penalty at the very beginning
        call penalty_calculation(l)
        call link_pricing
        call kspcost_main(dy_muc)
      endif

! --
! --  set time_now consistent with stage start (in the RH procedure)
! --
      if(iso_ok.eq.1.or.iue_ok.eq.1) time_now=stagest*60
! --
! -- call the loop to start from time 1 (first simulation interval) to 
! -- In case of real-time execution (ireal=1), the CORBA code will call the
! -- loop every display interval.
! --
   	  starttime=nint(stagest/tii)+1
      endtime=nint((stagest+stagelength)/tii)

      numof_siminterval = endtime - starttime + 1

! End
c	print *, 'Alex350'

      call loop(starttime,endtime,maxintervals)
 
c      print *, 'Alex400'

      write(666,*) '***************************************'
      write(666,*)
      write(666,*) 'VEHICLE LOADING MODE '
      write(666,*) '--------------------'
      if(realdm.eq.1) then
      write(666,'( "    O-D Demand Table                          ")')    
	  elseif(realdm.eq.0) then
      write(666,'("Vehicle File,Initial Path Generated by DYNASMART")') 
	  elseif(realdm.eq.2) then
      write(666,'( "    Vehicle + Path File                       ")')
	  endif
      write(666,*) '***************************************'
      write(666,*)
      write(666,*) 'MUC CLASS PERCENTAGES'
      write(666,*) '---------------------'

	  if(realdm.eq.1) then
! if load from OD table, then take values from scenario.dat
!      write(666,'( "    Pre-Specified (Non-Responsive)           : ",f8.2," %")') classpro(1)*100.0
!	  write(666,'( "    Boundedly-Rational(En-route Information) : ",f8.2," %")') (classpro(4)-classpro(3))*100.0
!	  write(666,'( "    VMS Responsive                           : ",f8.2," %")') (classpro(5)-classpro(4))*100.0
!	  write(666,'( "    System Optimal                           : ",f8.2," %")') (classpro(2)-classpro(1))*100.0
!	  write(666,'( "    User Equilibrium                         : ",f8.2," %")') (classpro(3)-classpro(2))*100.0
!      withinf=classpro(4)-classpro(3)
!      withoutinfo=1.0-withinf
      write(666,'("Pre-Specified (Non-Responsive)           
     +  : ",f8.2," %")') (100.0*muc_veh(1))/jj
	write(666,'("Boundedly-Rational(En-route Information) 
     +  : ",f8.2," %")') (100.0*muc_veh(4))/jj
	write(666,'("VMS Responsive                           
     +  : ",f8.2," %")') (100.0*muc_veh(5))/jj
	write(666,'("System Optimal                           
     +  : ",f8.2," %")') (100.0*muc_veh(2))/jj
	write(666,'("User Equilibrium                         
     +  : ",f8.2," %")') (100.0*muc_veh(3))/jj
      withinf=(100.0*muc_veh(4))/jj
      withoutinfo=1.0-(100.0*muc_veh(4))/jj
	  else
c if read from vehicle files, need to calcualte the percentage after loading all the vehicles
	  if(MaxVehicles.gt.0) then
      write(666,'( "    Pre-Specified (Non-Responsive)           
     +  : ",f8.2," %")') (100.0*muc_veh(1))/MaxVehicles
	  write(666,'( "    Boundedly-Rational(En-route Information) 
     +  : ",f8.2," %")') (100.0*muc_veh(4))/MaxVehicles
	  write(666,'( "    VMS Responsive                           
     +  : ",f8.2," %")') (100.0*muc_veh(5))/MaxVehicles
	  write(666,'( "    System Optimal                           
     +  : ",f8.2," %")') (100.0*muc_veh(2))/MaxVehicles
	  write(666,'( "    User Equilibrium                         
     +  : ",f8.2," %")') (100.0*muc_veh(3))/MaxVehicles
      withinf = muc_veh(4)/MaxVehicles
	  withoutinfo=1.0-withinf
	  else
      write(666,'("Pre-Specified (Non-Responsive) : ",f8.2," %")') 0.0
	write(666,'("Boundedly-Rational(En-route Information)
     + : ",f8.2," %")') 0.0
	write(666,'("VMS Responsive                          
     + : ",f8.2," %")') 0.0
	write(666,'("System Optimal                          
     + : ",f8.2," %")') 0.0
	write(666,'("User Equilibrium                        
     + : ",f8.2," %")') 0.0
      withinf = 0.0
	  withoutinfo = 0.0
	  endif

	  endif
      write(666,*) '***************************************'
      write(666,*)
      write(666,*) 'VEHICLE TYPE PERCENTAGES'
      write(666,*) '------------------------'
c
      if(realdm.eq.1)then ! if load from OD table, then take values from scenario.dat
	write(666,' ( "    PC : ",f9.1," %")') 
     +  (100.0*(Numof_Veh_Type(1)+Numof_Veh_Type(4))/jj)
        write(666,' ( "    TRUCK    : ",f9.1," %")') 
     +  (100.0*(Numof_Veh_Type(2)+Numof_Veh_Type(5))/jj)
        write(666,' ( "    HOV   : ",f9.1," %")') 
     +  (100.0*(Numof_Veh_Type(3)+Numof_Veh_Type(6))/jj)
       write(666,' ( "    BUS  : ",i7," Buses")') nubus

c	!******************************** start of addition **********************************
	  else ! if read from vehicle files, need to calcualte the percentage after loading all the vehicles
	     if(MaxVehicles.gt.0) then
	write(666,'( " PC   : ",f9.1,"%")') (100.0*
     +  (Numof_Veh_Type(1)+Numof_Veh_Type(4))/iread_veh_count)
        write(666,' ( "    TRUCK  : ",f9.1," %")') (100.0*
     +  (Numof_Veh_Type(2)+Numof_Veh_Type(5))/iread_veh_count)
        write(666,' ( "    HOV   : ",f9.1," %")') (100.0*
     + (Numof_Veh_Type(3)+Numof_Veh_Type(6))/iread_veh_count)
      write(666,' ( "    BUS  : ",i7," Buses")') nubus
		else
	  write(666,' ( "    PC  : ",f9.1," %")') 0.0
      write(666,' ( "    TRUCK   : ",f9.1," %")') 0.0
      write(666,' ( "    HOV     : ",f9.1," %")') 0.0
      write(666,' ( "    BUS  : ",i7," Buses")') nubus
		endif
	  endif
!********************************************* end of addition ***************************	  	
!************ end move********************
c	print *, 'Alex500'	  

      call final_statistics(maxintervals)	! for summarystat.dat
c	print *, 'Alex600'
! --  call summary to print RH related summary information      
      call summary(Maxintervals)		! for outMUC.dat

! End
c	print *, 'Alex700'

! --  call outputmuc to calculate # of vehicles for all orig, dest, assign int
      if(itedex.gt.0.and.iteration.eq.0.and.
     +  (iso_ok.eq.1.or.iue_ok.eq.1)) then
        call outputmuc
	  endif
c	print *, 'Alex701'

! Update the best MOE and iteration for MUC solutions
! we update current_MOE in summary.f90
	if(iso_ok.eq.1)then
		
		if(current_MOE<best_MOE)then
			best_MOE=current_MOE
			best_iteration=iteration
		endif

		! Output the best MUC iteration to summarystat.dat
	WRITE(666,*) '------------------------------------------------'
	WRITE(666,*)'Best MUC Solution (Please refer to outMUC.dat)'
	WRITE(666,'("Best Iteration                                 
     +  : ", i7)') best_iteration
	WRITE(666,'("Average Trip Time for vehicles reaching destinations: 
     +  ", f12.4)') best_MOE
	WRITE(666,*) '------------------------------------------------'
	endif

	close(666)
! End
c	print *, 'Alex702'

! -- call deall_dyna to deallocate memories taken by dynasmart
! -- except those used for muc
      call deallocate_dyna
c	print *, 'Alex800'
! -- call deallocate_ksp to deallocate memories taken by ksp
!      if(iteration.eq.0.or.noofstops.gt.1.or.classpro(4)-classpro(3).gt.0.001.or.vms_num.gt.0) then

!      if(iteration.eq.0.and.(realdm.ne.2.or.noofstops.gt.1.or.classpro(4)-classpro(3).gt.0.001.or.vms_num.gt.0)) then
      if((iteration.eq.0.and.(realdm.ne.2.or.noofstops.gt.1))
     +  .or.ienroute_ok.eq.1.or.vms_num.gt.0)then
c	print *, 'Alex800a'
        call deallocate_ksp1
c	print *, 'Alex900'
        call deallocate_ksp2
c	print *, 'Alex1000'
      endif
c	print *, 'Alex1100'
      deallocate(past_phase)

      return
      end
