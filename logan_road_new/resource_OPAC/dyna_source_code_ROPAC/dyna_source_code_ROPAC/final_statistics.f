	subroutine final_statistics(l)
! --
! -- This subroutine calculates the statitstics at the end of the 
! -- simulation.
! --
! -- This subroutine is called from loop 
! -- 
! -- This subroutine calls the following subroutines
! --   vehicle_trajectory()
! --   muc_output()
! --  
! --  INPUT :
! --      l : the last simulation interval number.
! --    all the other arrays are transeferred through the common blocks.
! --
! --  OUTPUT :
! --    fort.666 : summary output file (it is then moved to fort.6)
! --    fort.65 and fort.180 : summary statistics for MUC.
! -- 
    	use muc_mod
	use vector_mod
	real::www = 0
! --
! -- Output the files required for MUC, if any
! --
! -- Output the vehicle_trajectory file (fort.18) if the user speicifies
! -- the file to be produced (form the Optional Output Screen)
! --
c	print *, 'Alex510'	
       if(i18.eq.1) call vehicle_trajectory(l)
c	print *, 'Alex520'		   
! --
! -- non-optional output information 
! --

!      write(666,164)  fracinf,ribfa,bound
      write(666,164)  ribfa,bound

!164   FORMAT('FRACTION WITH INFO =',F6.3,'  AVG.IB-FRACTION =',F5.2,'   BOUND =',F5.2/)
164   FORMAT('AVG.IB-FRACTION =',F5.2,'   BOUND =',F5.2/)

! --
! -- If no cars exist in the network, then the cumulative statistics
! -- have been calculated for each vehicle when it went out of the network
! --
      if(numcars.eq.0) go to 172

      write(666,*) 'NOTE : There are', numcars,'  
     + target vehicles still in the network'
! --
! --
! --
      number_cars_total=0
      if(jj.ge.nu_ve) then
        number_cars_total=nu_ve
      else
        number_cars_total=jj
      endif
! --
! --
! --     
      do 171 j=1,number_cars_total

      www = 0

      if(notin(j).eq.1) go to 171

      if(itag(j).eq.1)then
        itag1=itag1+1
        if(NoOfIntDst(j).gt.1) then
	    do ka=1,NoOfIntDst(j)-1
            www=www+IntDestDwell(j,ka)
          enddo
        endif
        stoptemp = ttstop(j)
	    stoptime=stoptime+ttstop(j)
        if(atime(j).gt.0) then
          ttt=max(0.0,atime(j)-stime(j)-ttilnow(j)-www)  ! only difference 
	      tt =max(0.0,atime(j)-stime(j)-www)             ! with get_veh_stat
        else                                             !
          ttt=max(0.0,l*tii-stime(j)-ttilnow(j)-www)     !
	      tt =max(0.0,l*tii-stime(j)-www)                ! 
        endif                                            !
        entry_queue1=entry_queue1+ttt
        triptime1=triptime1+tt
        dtotal1=dtotal1+distans(j)
        vtothr1=vtothr1+ttilnow(j)

!        itag2=itag2+1

        if(info(j).eq.1) then
	     entry_queue2=entry_queue2+ttt
           triptime2=triptime2+tt
           information=information+1
           vtothr2=vtothr2+ttilnow(j)
           dtotal2=dtotal2+distans(j)
           stopinfo=stopinfo+stoptemp
           switch(j)=iabs(switch(j))-1
           totaldecision=decision(j)+totaldecision
           totalswitch=switch(j)+totalswitch
           if(NoOfIntDst(j).eq.1) then
                             entry_queue2_1=entry_queue2_1+ttt
                             triptime2_1=triptime2_1+tt
                             information_1=information_1+1
                             vtothr2_1=vtothr2_1+ttilnow(j)
                             dtotal2_1=dtotal2_1+distans(j)
                             stopinfo_1=stopinfo_1+stoptemp
           elseif(NoOfIntDst(j).eq.2) then
                             entry_queue2_2=entry_queue2_2+ttt
                             triptime2_2=triptime2_2+tt
                             information_2=information_2+1
                             vtothr2_2=vtothr2_2+ttilnow(j)
                             dtotal2_2=dtotal2_2+distans(j)
                             stopinfo_2=stopinfo_2+stoptemp
           elseif(NoOfIntDst(j).eq.3) then
                             entry_queue2_3=entry_queue2_3+ttt
                             triptime2_3=triptime2_3+tt
                             information_3=information_3+1
                             vtothr2_3=vtothr2_3+ttilnow(j)
                             dtotal2_3=dtotal2_3+distans(j)
                             stopinfo_3=stopinfo_3+stoptemp
           endif
           do is=1,nu_switch+1
             if(switch(j).eq.is-1) switchnum(is)=switchnum(is)+1
           enddo
           do is=1,nu_switch+1
             if(decision(j).eq.is-1) decisionnum(is)=decisionnum(is)+1
           enddo
           if(switch(j).gt.nu_switch) switchnum(nu_switch+1)=
     +  switchnum(nu_switch+1)+1
           if(decision(j).gt.nu_switch) decisionnum(nu_switch+1)=
     +  decisionnum(nu_switch+1)+1

        elseif(info(j).eq.0) then
	     entry_queue3=entry_queue3+ttt
           triptime3=triptime3+tt
           noinformation=noinformation+1
           vtothr3=vtothr3+ttilnow(j)
           dtotal3=dtotal3+distans(j)
           stopnoinfo=stopnoinfo+stoptemp
           if(NoOfIntDst(j).eq.1) then
                             entry_queue3_1=entry_queue3_1+ttt
                             triptime3_1=triptime3_1+tt
                             noinformation_1=noinformation_1+1
                             vtothr3_1=vtothr3_1+ttilnow(j)
                             dtotal3_1=dtotal3_1+distans(j)
                             stopnoinfo_1=stopnoinfo_1+stoptemp
           elseif(NoOfIntDst(j).eq.2) then
                             entry_queue3_2=entry_queue3_2+ttt
                             triptime3_2=triptime3_2+tt
                             noinformation_2=noinformation_2+1
                             vtothr3_2=vtothr3_2+ttilnow(j)
                             dtotal3_2=dtotal3_2+distans(j)
                             stopnoinfo_2=stopnoinfo_2+stoptemp
           elseif(NoOfIntDst(j).eq.3) then
                             entry_queue3_3=entry_queue3_3+ttt
                             triptime3_3=triptime3_3+tt
                             noinformation_3=noinformation_3+1
                             vtothr3_3=vtothr3_3+ttilnow(j)
                             dtotal3_3=dtotal3_3+distans(j)
                             stopnoinfo_2=stopnoinfo_2+stoptemp
           endif
        endif

	elseif(itag(j).eq.0) then

        itag0=itag0+1

	endif

171   continue
172   continue
! --
! - -- --- -- -- -- - -- -- -- -- - -- 
        if((noinformation+information).gt.0)then
           vavg1=vtothr1/float(information+noinformation)
           avedtotal1=dtotal1/(noinformation+information)
           ave_entry1=entry_queue1/float(noinformation+information)
           ave_trip1=triptime1/float(noinformation+information)
           avestoptime=stoptime/(noinformation+information)
        endif
! --
! --
        if(information.gt.0)then
          vavg2=vtothr2/float(information)
          avedtotal2=dtotal2/information
          ave_entry2=entry_queue2/float(information)
          ave_trip2=triptime2/float(information)
          avestopinfo=stopinfo/information
        endif
! --
! --
        if(information_1.gt.0) then
          vavg2_1=vtothr2_1/float(information_1)
          avedtotal2_1=dtotal2_1/float(information_1)
          ave_entry2_1=entry_queue2_1/float(information_1)
          ave_trip2_1=triptime2_1/float(information_1)
          avestopinfo_1=stopinfo_1/float(information_1)
        endif
! --
        if(information_2.gt.0) then
          vavg2_2=vtothr2_2/float(information_2)
          avedtotal2_2=dtotal2_2/float(information_2)
          ave_entry2_2=entry_queue2_2/float(information_2)
          ave_trip2_2=triptime2_2/float(information_2)
          avestopinfo_2=stopinfo_2/float(information_2)
        endif
! --
        if(information_3.gt.0) then
          vavg2_3=vtothr2_3/float(information_3)
          avedtotal2_3=dtotal2_3/float(information_3)
          ave_entry2_3=entry_queue2_3/float(information_3)
          ave_trip2_3=triptime2_3/float(information_3)
          avestopinfo_3=stopinfo_3/float(information_3)
        endif
! --
        if(noinformation.GT.0) then 
          vavg3=vtothr3/float(noinformation)
          avedtotal3=dtotal3/float(noinformation)
          ave_entry3=entry_queue3/float(noinformation)
          ave_trip3=triptime3/float(noinformation)
          avestopnoinfo=stopnoinfo/float(noinformation)
        endif
! --
! --
        if(noinformation_1.GT.0) then 
          vavg3_1=vtothr3_1/float(noinformation_1)
          avedtotal3_1=dtotal3_1/float(noinformation_1)
          ave_entry3_1=entry_queue3_1/float(noinformation_1)
          ave_trip3_1=triptime3_1/float(noinformation_1)
          avestopnoinfo_1=stopnoinfo_1/float(noinformation_1)
        endif
! --
! --
        if(noinformation_2.GT.0) then 
          vavg3_2=vtothr3_2/float(noinformation_2)
          avedtotal3_2=dtotal3_2/float(noinformation_2)
          ave_entry3_2=entry_queue3_2/float(noinformation_2)
          ave_trip3_2=triptime3_2/float(noinformation_2)
          avestopnoinfo_2=stopnoinfo_2/float(noinformation_2)
        endif
! --
        if(noinformation_3.GT.0) then 
          vavg3_3=vtothr3_3/float(noinformation_3)
          avedtotal3_3=dtotal3_3/float(noinformation_3)
          ave_entry3_3=entry_queue3_3/float(noinformation_3)
          ave_trip3_3=triptime3_3/float(noinformation_3)
          avestopnoinfo_3=stopnoinfo_3/float(noinformation_3)
        endif
! --
      write(666,*) ' '
      write(666,*) ' ******* VEHICLE INFORMATION ******* '
      write(666,*) ' 	TOTAL VEHICLES        : ',jj
      write(666,*) ' 	NON-TAGGED VEHICLES   : ',itag0
      write(666,*) ' 	TAGGED VEHICLES (IN)  : ',itag1
      write(666,*) ' 	TAGGED VEHICLES (OUT) : ',itag2
      write(666,*) ' 	OTHERS                : ',itag3
      write(666,*)
! --
! --
    	if(iactual_hov.gt.0.0) then
      write(666,*) ' '
      write(666,*) ' ******* HOV/LOV VEHICLE INFORMATION ******* '

    	if(iactual_lov.gt.0.0) then
      write(666,'( "    Avg travel time for LOV                     
     +  : ",f12.4)')time_lov/iactual_lov
    	else 
      write(666,'("Avg travel time for LOV :  N/A")')
    	endif
      write(666,*)
	endif
    
	if(iactual_hov.gt.0.0) then
      write(666,'( "    Avg travel time for HOV                     
     +  : ",f12.4)')time_hov/iactual_hov
    	else 
      write(666,'("Avg travel time for HOV :       N/A")')
    	endif
      write(666,*)

	if(link_hot.gt.0) then

      write(666,*) ' ******* HOT LANE(S) INFORMATION  ********** '
      write(666,'("Number of Links with Toll : ",i7)') link_hot
      write(666,*)
      write(666,*) '   For the Vehicles Exit the Network'
      write(666,*)
      write(666,'("Number of LOV in HOT lanes : ",i7)')iactual_lov_hot
    	if(iactual_lov_hot.gt.0.0) then
      write(666,'( "    Avg travel time for LOV in the HOT lane     
     +  : ",f12.4)')time_lov_hot/iactual_lov_hot
    	else 
      write(666,'("Avg travel time for LOV in the HOT lane : N/A")')
    	endif
      write(666,*)
      write(666,'( "    Number of LOV not in HOT lanes              
     + : ",i7)')iactual_lov_ohot
    	if(iactual_lov_ohot.gt.0.0) then
      write(666,'( "    Avg travel time for LOV not in the HOT lane 
     + : ",f12.4)')time_lov_ohot/iactual_lov_ohot 
    	else 
      write(666,'("Avg travel time for LOV not in the HOT lane : N/A")')
    	endif
      write(666,*)
      write(666,'( "    Number of HOV in HOT lanes                  
     + : ",i7)')iactual_hov_hot
    	if(iactual_hov_hot.gt.0.0) then
      write(666,'( "    Avg travel time for HOV in the HOT lane     
     + : ",f12.4)')time_hov_hot/iactual_hov_hot
    	else 
      write(666,'("Avg travel time for HOV in the HOT lane : N/A")') 
    	endif
      write(666,*) 
      write(666,'( "    Number of HOV not in HOT lanes              
     +  : ",i7)')iactual_hov_ohot
    	if(iactual_hov_ohot.gt.0.0) then
      write(666,'( "    Avg travel time for HOV not in the HOT lane 
     +  : ",f12.4)')time_hov_ohot/iactual_hov_ohot
    	else
      write(666,'("Avg travel time for HOV not in the HOT lane : N/A")') 
    	endif

	endif
      write(666,*)
      WRITE(666,*) '***************************************'
      WRITE(666,*) '*  OVERALL STATISTICS REPORT          *'
      WRITE(666,*) '***************************************'
      WRITE(666,*) ' '
      write(666,'( "    Max Simulation Time (min)                  
     +  : ",f10.1)') stagelength
      write(666,'( "    Actual Sim. Intervals                      
     +  : ",i8)') L
      write(666,'( "    Simulation Time     (min)                  
     +  : ",f10.1)') L*tii
      write(666,'( "    Start Time in Which Veh Stat are Collected 
     +  : ",f10.1)') starttm
      write(666,'( "    End   Time in Which Veh Stat are Collected 
     +  : ",f10.1)') endtm
      write(666,'( "    Total Number of Vehicles of Interest       
     +  : ",i8)') INFORMATION+NOINFORMATION
      write(666,'( "                            With    Info       
     +  : ",i8)') INFORMATION
      write(666,'( "                            Without Info       
     +  : ",i8)') NOINFORMATION
      WRITE(666,*) '------------------------------------------------'
      WRITE(666,*) 'TOTAL TRAVEL TIMES (HRS)'
      WRITE(666,'( "    OVERALL    : ",f12.4)')VTOTHR1/60.0
      WRITE(666,'( "    NOINFO     : ",f12.4)')VTOTHR3/60.0
      WRITE(666,'( "    1 stop     : ",f12.4)')VTOTHR3_1/60.0
      WRITE(666,'( "    2 stops    : ",f12.4)')VTOTHR3_2/60.0
      WRITE(666,'( "    3 stops    : ",f12.4)')VTOTHR3_3/60.0
      WRITE(666,'( "    INFO       : ",f12.4)')VTOTHR2/60.0
      WRITE(666,'( "    1 stop     : ",f12.4)')VTOTHR2_1/60.0
      WRITE(666,'( "    2 stops    : ",f12.4)')VTOTHR2_2/60.0
      WRITE(666,'( "    3 stops    : ",f12.4)')VTOTHR2_3/60.0
      WRITE(666,*) 
      WRITE(666,*) 'AVERAGE TRAVEL TIMES (MINS)'
      WRITE(666,'( "    OVERALL    : ",f12.4)')VAVG1
      WRITE(666,'( "    NOINFO     : ",f12.4)')VAVG3
      WRITE(666,'( "    1 stop     : ",f12.4)')VAVG3_1
      WRITE(666,'( "    2 stops    : ",f12.4)')VAVG3_2
      WRITE(666,'( "    3 stops    : ",f12.4)')VAVG3_3
      WRITE(666,'( "    INFO       : ",f12.4)')VAVG2
      WRITE(666,'( "    1 stop     : ",f12.4)')VAVG2_1
      WRITE(666,'( "    2 stops    : ",f12.4)')VAVG2_2
      WRITE(666,'( "    3 stops    : ",f12.4)')VAVG2_3
      WRITE(666,*) 
      WRITE(666,*) '------------------------------------------------'
      WRITE(666,*)'TOTAL TRIP TIMES(INCLUDING ENTRY QUEUE TIME) (HRS)'
      WRITE(666,'( "    OVERALL    : ",f12.4)')triptime1/60
      WRITE(666,'( "    NOINFO     : ",f12.4)')triptime3/60
      WRITE(666,'( "    1 stop     : ",f12.4)')triptime3_1/60.0
      WRITE(666,'( "    2 stops    : ",f12.4)')triptime3_2/60.0
      WRITE(666,'( "    3 stops    : ",f12.4)')triptime3_3/60.0
      WRITE(666,'( "    INFO       : ",f12.4)')triptime2/60
      WRITE(666,'( "    1 stop     : ",f12.4)')triptime2_1/60.0
      WRITE(666,'( "    2 stops    : ",f12.4)')triptime2_2/60.0
      WRITE(666,'( "    3 stops    : ",f12.4)')triptime2_3/60.0
      WRITE(666,*)'AVERAGE TRIP TIMES(INCLUDING ENTRY QUEUE TIME)(MINS)'
      WRITE(666,'( "    OVERALL    : ",f12.4)')ave_trip1
      WRITE(666,'( "    NOINFO     : ",f12.4)')ave_trip3
      WRITE(666,'( "    1 stop     : ",f12.4)')ave_trip3_1
      WRITE(666,'( "    2 stops    : ",f12.4)')ave_trip3_2
      WRITE(666,'( "    3 stops    : ",f12.4)')ave_trip3_3
      WRITE(666,'( "    INFO       : ",f12.4)')ave_trip2
      WRITE(666,'( "    1 stop     : ",f12.4)')ave_trip2_1
      WRITE(666,'( "    2 stops    : ",f12.4)')ave_trip2_2
      WRITE(666,'( "    3 stops    : ",f12.4)')ave_trip2_3
      WRITE(666,*) 
      WRITE(666,*) '---------------------------------------------'
      WRITE(666,*) 'TOTAL ENTRY QUEUE TIMES (HRS)'
      WRITE(666,'( "    OVERALL    : ",f12.4)')entry_queue1/60
      WRITE(666,'( "    NOINFO     : ",f12.4)')entry_queue3/60
      WRITE(666,'( "    1 stop     : ",f12.4)')entry_queue3_1/60.0
      WRITE(666,'( "    2 stops    : ",f12.4)')entry_queue3_2/60.0
      WRITE(666,'( "    3 stops    : ",f12.4)')entry_queue3_3/60.0
      WRITE(666,'( "    INFO       : ",f12.4)')entry_queue2/60
      WRITE(666,'( "    1 stop     : ",f12.4)')entry_queue2_1/60.0
      WRITE(666,'( "    2 stops    : ",f12.4)')entry_queue2_2/60.0
      WRITE(666,'( "    3 stops    : ",f12.4)')entry_queue2_3/60.0
      WRITE(666,*) 'AVERAGE ENTRY QUEUE TIMES (MINS)'
      WRITE(666,'( "    OVERALL    : ",f12.4)')ave_entry1
      WRITE(666,'( "    NOINFO     : ",f12.4)')ave_entry3
      WRITE(666,'( "    1 stop     : ",f12.4)')ave_entry3_1
      WRITE(666,'( "    2 stops    : ",f12.4)')ave_entry3_2
      WRITE(666,'( "    3 stops    : ",f12.4)')ave_entry3_3
      WRITE(666,'( "    INFO       : ",f12.4)')ave_entry2
      WRITE(666,'( "    1 stop     : ",f12.4)')ave_entry2_1
      WRITE(666,'( "    2 stops    : ",f12.4)')ave_entry2_2
      WRITE(666,'( "    3 stops    : ",f12.4)')ave_entry2_3
      WRITE(666,*) 
      WRITE(666,*) '----------------------------------------------'
      WRITE(666,*) 'TOTAL STOP TIME ( HRS )'
      WRITE(666,'( "    OVERALL    : ",f12.4)')stoptime/60.0
      WRITE(666,'( "    NOINFO     : ",f12.4)')stopnoinfo/60.0
      WRITE(666,'( "    1 stop     : ",f12.4)')stopnoinfo_1/60.0
      WRITE(666,'( "    2 stops    : ",f12.4)')stopnoinfo_2/60.0
      WRITE(666,'( "    3 stops    : ",f12.4)')stopnoinfo_3/60.0
      WRITE(666,'( "    INFO       : ",f12.4)')stopinfo/60.0
      WRITE(666,'( "    1 stop     : ",f12.4)')stopinfo_1/60.0
      WRITE(666,'( "    2 stops    : ",f12.4)')stopinfo_2/60.0
      WRITE(666,'( "    3 stops    : ",f12.4)')stopinfo_3/60.0
      WRITE(666,*) 'AVERAGE STOP TIME ( MINS )'
      WRITE(666,'( "    OVERALL    : ",f12.4)')avestoptime
      WRITE(666,'( "    NOINFO     : ",f12.4)')avestopnoinfo
      WRITE(666,'( "    1 stop     : ",f12.4)')avestopnoinfo_1
      WRITE(666,'( "    2 stops    : ",f12.4)')avestopnoinfo_2
      WRITE(666,'( "    3 stops    : ",f12.4)')avestopnoinfo_3
      WRITE(666,'( "    INFO       : ",f12.4)')avestopinfo
      WRITE(666,'( "    1 stop     : ",f12.4)')avestopinfo_1
      WRITE(666,'( "    2 stops    : ",f12.4)')avestopinfo_2
      WRITE(666,'( "    3 stops    : ",f12.4)')avestopinfo_3
      write(666,*) 
      WRITE(666,*) '----------------------------------------------'
      WRITE(666,*) 'TOTAL TRIP DISTANCE ( MILES )'
      WRITE(666,'( "    OVERALL    : ",f12.4)')dtotal1
      WRITE(666,'( "    NOINFO     : ",f12.4)')dtotal3
      WRITE(666,'( "    1 stop     : ",f12.4)')dtotal3_1
      WRITE(666,'( "    2 stops    : ",f12.4)')dtotal3_2
      WRITE(666,'( "    3 stops    : ",f12.4)')dtotal3_3
      WRITE(666,'( "    INFO       : ",f12.4)')dtotal2
      WRITE(666,'( "    1 stop     : ",f12.4)')dtotal2_1
      WRITE(666,'( "    2 stops    : ",f12.4)')dtotal2_2
      WRITE(666,'( "    3 stops    : ",f12.4)')dtotal2_3
      WRITE(666,*) 'AVERAGE TRIP DISTANCE ( MILES )'
      WRITE(666,'( "    OVERALL    : ",f12.4)')avedtotal1
      WRITE(666,'( "    NOINFO     : ",f12.4)')avedtotal3
      WRITE(666,'( "    1 stop     : ",f12.4)')avedtotal3_1
      WRITE(666,'( "    2 stops    : ",f12.4)')avedtotal3_2
      WRITE(666,'( "    3 stops    : ",f12.4)')avedtotal3_3
      WRITE(666,'( "    INFO       : ",f12.4)')avedtotal2
      WRITE(666,'( "    1 stop     : ",f12.4)')avedtotal2_1
      WRITE(666,'( "    2 stops    : ",f12.4)')avedtotal2_2
      WRITE(666,'( "    3 stops    : ",f12.4)')avedtotal2_3
      WRITE(666,*)
      WRITE(666,*) '---------------------------------------------'
c --
c	print *, 'Alex550'	
      call write_vehicles() 
c --
432   return 
      END 
