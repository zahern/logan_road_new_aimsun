      subroutine summary(ctime)
 
      use muc_mod
      use vector_mod
! --
! -- output information
! --
      integer ctime
! --  The second dimension is for HOV/LOV
!     1: LOV
!     2: HOV 
      real,dimension(nu_classes,2)::timeclass,disclass,stoptimeclass,
     + timeentry,totaltimeclass
      integer, dimension(nu_classes,2)::numberclass
      integer AllNumberIMP
	real AlltimeIMP,AlldistIMP,AllstopIMP
! -  
      real,allocatable::timeIMP(:,:),distIMP(:,:),stopIMP(:,:),
     + entryIMP(:,:),totalIMP(:,:)
      real,allocatable::WZtimeIMP(:,:),WZdistIMP(:,:),
     + WZstopIMP(:,:),WZentryIMP(:,:),WZtotalIMP(:,:)
	  integer,allocatable::numberIMP(:,:)
	  integer,allocatable::WZnumberIMP(:,:)
      if(inci_num.gt.0) then
	    allocate(timeIMP(2,inci_num))
	  timeIMP(:,:) = 0.0
	    allocate(distIMP(2,inci_num))
	  distIMP(:,:)=0.0
	    allocate(stopIMP(2,inci_num))
	  stopIMP(:,:) = 0.0
	    allocate(entryIMP(2,inci_num))
	  entryIMP(:,:) = 0.0
	    allocate(totalIMP(2,inci_num))
	  totalIMP(:,:) = 0.0
            allocate(numberIMP(2,inci_num))
      	  numberIMP(:,:) = 0.0
	  endif
      if(WorkZoneNum.gt.0) then
	    allocate(WZtimeIMP(2,WorkZoneNum))
	  WZtimeIMP(:,:) = 0.0
	    allocate(WZdistIMP(2,WorkZoneNum))
	  WZdistIMP(:,:) = 0.0
	    allocate(WZstopIMP(2,WorkZoneNum))
	  WZstopIMP(:,:) = 0.0
	    allocate(WZentryIMP(2,WorkZoneNum))
	  WZentryIMP(:,:) = 0.0
	    allocate(WZtotalIMP(2,WorkZoneNum))
	  WZtotalIMP(:,:) = 0.0
            allocate(WZnumberIMP(2,WorkZoneNum))
          WZnumberIMP(:,:) = 0.0
	  endif

c 	print *, 'Alex601'
      
	AlltimeIMP  = 0
	AlldistIMP  = 0
	AllstopIMP  = 0
      timeclass(:,:) = 0.0
      numberclass(:,:) = 0
      disclass(:,:) = 0.0
      stoptimeclass(:,:) = 0.0
      timeentry(:,:) =0.0
      totaltimeclass(:,:) = 0.0 
! -- 
C 	print *, 'Alex6014'
! --
          
	  I_Tag_1_Stage=0
	  I_Tag_2_Stage=0
	  I_Tag_1_Roll=0
	  I_Tag_2_Roll=0
C 	print *, 'Alex6015'
	  Trip_Time_Total=0.0
	  Trip_Time_Total_Itag1=0.0
	  Trip_Time_Total_Itag2=0.0
	  Trip_Time_Roll=0.0
	  Trip_Time_Roll_Itag1=0.0
	  Trip_Time_Roll_Itag2=0.0
C 	print *, 'Alex6016'
	  Trip_Time_Total_W_Q=0.0
	  Trip_Time_Roll_W_Q=0.0
C 	print *, 'Alex6017'
	  Trip_Distance_Total=0.0
	  Trip_Distance_Total_Itag1=0.0
	  Trip_Distance_Total_Itag2=0.0
	  Trip_Distance_Roll=0.0
	  Trip_Distance_Roll_Itag1=0.0
	  Trip_Distance_Roll_Itag2=0.0
C 	print *, 'Alex6018'
         Stop_Time_Total=0.0
         Stop_Time_Total_Itag1=0.0
         Stop_Time_Total_Itag2=0.0
         Stop_Time_Roll=0.0
         Stop_Time_Roll_Itag1=0.0
         Stop_Time_Roll_Itag2=0.0

c 	print *, 'Alex602',jj
	
      do 200 i=1,jj
	  if(stime(i).ge.starttm.and.stime(i).lt.endtm) then
       if(itag(i).eq.2) then
        ihov = ioc(i)
        iv=vehclass(i)      
        totaltimeclass(iv,ihov)=
     +  totaltimeclass(iv,ihov)+(atime(i)-stime(i))
        timeclass(iv,ihov)=timeclass(iv,ihov)+ttilnow(i)
        numberclass(iv,ihov)=numberclass(iv,ihov)+1
        disclass(iv,ihov)=disclass(iv,ihov)+distans(i)
        stoptimeclass(iv,ihov)=stoptimeclass(iv,ihov)+
     +  VhcAtt_value(i,VhcAtt_Size(i)-1,2)
        ttt=max(0.0,atime(i)-stime(i)-ttilnow(i))
        timeentry(iv,ihov)=timeentry(iv,ihov)+ttt
       endif


	  if (itag(i).eq.1) then
	   I_Tag_1_Stage=I_Tag_1_Stage+1
	   Trip_Time_Total_Itag1=Trip_Time_Total_Itag1+Ttilnow(i)
       Trip_Distance_Total_Itag1=Trip_Distance_Total_Itag1+Distans(i)
       Stop_Time_Total_Itag1=Stop_Time_Total_Itag1+
     +  VhcAtt_value(i,VhcAtt_Size(i)-1,2)
	  endif


  	  if (itag(i).eq.2) then
	   I_Tag_2_Stage=I_Tag_2_Stage+1
	   Trip_Time_Total_W_Q=Trip_Time_Total_W_Q+Atime(i)-Stime(i)
	   Trip_Time_Total_Itag2=Trip_Time_Total_Itag2+Ttilnow(i)
       Trip_Distance_Total_Itag2=Trip_Distance_Total_Itag2+Distans(i)
       Stop_Time_Total_Itag2=Stop_Time_Total_Itag2+
     +  VhcAtt_value(i,VhcAtt_Size(i)-1,2)
	  endif


! --  calculating statistics for impacted vehicles
      
      if(inci_num.gt.0) then
      if(ImpactType(i)%InciMode.ne.0.and.
     + ImpactType(i)%InciIM.ne.0) then
         IQ1 = ImpactType(i)%InciMode
		 IQ2 = ImpactType(i)%InciIM
	       timeIMP(IQ1,IQ2) = timeIMP(IQ1,IQ2) + ttilnow(i)
	       distIMP(IQ1,IQ2) = distIMP(IQ1,IQ2) + distans(i)
	       stopIMP(IQ1,IQ2) = stopIMP(IQ1,IQ2) + 
     +  VhcAtt_value(i,VhcAtt_Size(i)-1,2)
           numberIMP(IQ1,IQ2) = numberIMP(IQ1,IQ2) + 1
		   if(itag(i).eq.2) then
	totalIMP(IQ1,IQ2)=totalIMP(IQ1,IQ2)+(atime(i)-stime(i))
		   endif
	  endif
	  endif

      if(WorkZoneNum.gt.0) then
      if(ImpactType(i)%WZMode.ne.0.and.ImpactType(i)%WZIM.ne.0) then
         IQ1 = ImpactType(i)%WZMode
		 

		 IQ2 = ImpactType(i)%WZIM
	       WZtimeIMP(IQ1,IQ2) = WZtimeIMP(IQ1,IQ2) + ttilnow(i)
	       WZdistIMP(IQ1,IQ2) = WZdistIMP(IQ1,IQ2) + distans(i)
	       WZstopIMP(IQ1,IQ2) = WZstopIMP(IQ1,IQ2) + 
     + VhcAtt_value(i,VhcAtt_Size(i)-1,2)
           WZnumberIMP(IQ1,IQ2) = WZnumberIMP(IQ1,IQ2) + 1
		   if(itag(i).eq.2) then
	WZtotalIMP(IQ1,IQ2)=WZtotalIMP(IQ1,IQ2)+(atime(i)-stime(i))
		   endif
	  endif
	  endif
      endif
200   continue

c 	print *, 'Alex603'

	  I_Tag_Roll=I_Tag_1_Roll+I_Tag_2_Roll
	  I_Tag_Total=I_Tag_1_Stage+I_Tag_2_Stage
	  Trip_Time_Total=Trip_Time_Total_Itag1+Trip_Time_Total_Itag2
	  Trip_Time_Roll=Trip_Time_Roll_Itag1+Trip_Time_Roll_Itag2
       Trip_Distance_Total=
     +Trip_Distance_Total_Itag1+Trip_Distance_Total_Itag2
       Trip_Distance_Roll=
     +Trip_Distance_Roll_Itag1+Trip_Distance_Roll_Itag2
       Stop_Time_Roll=Stop_Time_Roll_Itag1+Stop_Time_Roll_Itag2
       Stop_Time_Total=Stop_Time_Total_Itag1+Stop_Time_Total_Itag2


      write(180,*) '**********************************************'
      write(180,*) '**  Summaries for MUC Iteration Procedures  **'
      write(180,*) '**********************************************'
      write(180,*) 'BASIC PARAMETERS'
      write(180,*) ' Planning Horizon: ', horizon
!      write(180,*) ' Roll Period     : ', roll
!      write(180,*) ' Stage Length    : ', stagelength
      write(180,*) ' Iterations Limt.: ', itedex
      write(180,*) ' Loading Factor  : ', multi
	  write(180,*) ' Start Time of Collecting Stats:', starttm
	  write(180,*) ' End   Time of Collecting Stats:', endtm
	  write(180,*) ' Iteration:', iteration
      write(180,*) ' Current time:', float(ctime-1)/10
      write(180,*) '-----------------------------------------------'
      write (180,*) ' '
	  write (180,*) '  Vehicles Still in the Network   '
	  Write (180,'("     Number of Vehicles             
     + = ",i15)') I_Tag_1_Stage
	  Write (180,'("     Total Travel Time w/o queueing 
     + = ",f15.3)')Trip_Time_Total_Itag1
	  Write (180,'("     Total Trip Distances           
     + = ",f15.3)')Trip_Distance_Total_Itag1
       Write (180,'("     Total Stop Time                
     + = ",f15.3)')Stop_Time_Total_Itag1

       If (I_Tag_1_Stage.gt.0) then
        Write (180,'("     Average Travel Time            
     + = ",f15.3)')Trip_Time_Total_Itag1/I_Tag_1_Stage	    
		Write (180,'("     Average Trip Distance          
     + = ",f15.3)')Trip_Distance_Total_Itag1/I_Tag_1_Stage
        Write (180,'("     Average Stop Time              
     + = ",f15.3)')Stop_Time_Total_Itag1/I_Tag_1_Stage
        if(Trip_Time_Total_Itag1.ne.0.0) then   
          Write (180,'("     Average travel Speed           
     + = ",f15.3)')Trip_Distance_Total_Itag1/Trip_Time_Total_Itag1*60
        endif 
	  endif
	
       Write (180,*) '-----------------------------------------------'
	  write (180,*) '  Vehicles Outside the Network   '
       Write (180,'("     Number of Vehicles             
     + = ",i15)') I_Tag_2_Stage
	  Write (180,'("     Total Travel Time w/o queueing 
     + = ",f15.3)') Trip_Time_Total_Itag2
	  Write (180,'("     Total Travel Time w queueing   
     + = ",f15.3)') Trip_Time_Total_W_Q
	  Write (180,'("     Total Trip Distances           
     + = ",f15.3)') Trip_Distance_Total_Itag2
       Write (180,'("     Total Stop Time                
     + = ",f15.3)') Stop_Time_Total_Itag2
       If (I_Tag_2_Stage.gt.0) then
	    write (180,'("     Average Travel Time            
     + = ",f15.3)') Trip_Time_Total_Itag2/I_Tag_2_Stage


		Write (180,'("     Average Trip Time              
     + = ",f15.3)') Trip_Time_Total_W_Q/I_Tag_2_Stage
! End	    
		
		Write (180,'("     Average Trip Distance          
     + = ",f15.3)') Trip_Distance_Total_Itag2/I_Tag_2_Stage
        Write (180,'("     Average Stop Time              
     + = ",f15.3)') Stop_Time_Total_Itag2/I_Tag_2_Stage
        if(Trip_Time_Total_Itag2.ne.0.0) then   
          Write (180,'("     Average travel Speed           
     + = ",f15.3)') Trip_Distance_Total_Itag2/Trip_Time_Total_Itag2*60
        endif
	  endif


	current_MOE = Trip_Time_Total_W_Q / I_Tag_2_Stage	! Avg trip time
! End

	  Write (180,*) '-----------------------------------------------'
	  Write (180,*)
	  Write (180,*)' For All Vehicles in the Network   '
	  Write (180,'("     Number of Vehicles             
     + = ",i15)') I_Tag_Total
	  Write (180,'("     Total Travel Time w/o queueing 
     + = ",f15.3)') Trip_Time_Total
	  Write (180,'("     Total Trip Distances           
     + = ",f15.3)') Trip_Distance_Total
       Write (180,'("     Total Stop Time                
     + = ",f15.3)') Stop_Time_Total
       If (I_Tag_Total.gt.0) then
	    Write (180,'("     Average Travel Time            
     + = ",f15.3)') Trip_Time_Total/I_Tag_Total	    		
		Write (180,'("     Average Trip Distance          
     + = ",f15.3)') Trip_Distance_Total/I_Tag_Total
        Write (180,'("     Average Stop Time              
     + = ",f15.3)') Stop_Time_Total/I_Tag_Total
        if(Trip_Time_Total.ne.0.0) then    
          Write (180,'("     Average travel Speed           
     + = ",f15.3)') Trip_Distance_Total/Trip_Time_Total*60
        endif
	  Endif
      Write (180,*) '-------------------------------------------------'
      write (180,*) 'The following MUC information is only for	    '
      write (180,*) 'Those vehicles that have reached the destinations'
      write (180,*) '-------------------------------------------------'

c 	print *, 'Alex604'

      do 1201 ii=1,2
	    write(180,*)
	    write(180,*)
      if(ii.eq.1) write(180,*) ' LOV Vehicles -------------------------'
      if(ii.eq.2) write(180,*) ' HOV Vehicles -------------------------'
        do 1200 i=1,nu_classes    
          write(180,*)' ----------------------------------------------'


!          write(180,'(" Class Number                 = ",i15)') i

		  if(i.eq.1) then
          write(180,*) 
          write(180,*) 'Non-Responsive Vehicles'
		  write(180,*) 
		  elseif(i.eq.2) then
          write(180,*) 
		  write(180,*) 'System Optimal Vehicles'
          write(180,*) 
		  elseif(i.eq.3) then
          write(180,*) 
          write(180,*)'User Equilibrium Vehicles'
          write(180,*) 
		  elseif(i.eq.4) then
          write(180,*) 
		  write(180,*)'En-Route Info Vehicles' 
          write(180,*) 
    	  elseif(i.eq.5) then
          write(180,*) 
          write(180,*)'VMS-Responsive Vehicles'
          write(180,*) 
		  endif

          nc=numberclass(i,ii)
          if(nc.eq.0) goto 1200
          write(180,'(" Number of Vehicles         = ",i15)') nc
          write(180,*)'------------------'
	  write(180,'("Total Overall Travel Time(min)
     + = ",f15.3)') totaltimeclass(i,ii)
          write(180,'("Total Trip Times(min)         
     + = ",f15.3)') timeclass(i,ii)
          write(180,'("Total Entry Queue Time(min)   
     + = ",f15.3)') timeentry(i,ii)
          write(180,'("Total Trip Distance(ml)       
     + = ",f15.3)') disclass(i,ii)
          write(180,'("Total Stop Time(min)          
     + = ",f15.3)') stoptimeclass(i,ii)
          write(180,'("Average Overall Trip Time(min)
     + = ",f15.3)') totaltimeclass(i,ii)/nc
          write(180,'("Average Trip Times(min)       
     + = ",f15.3)') timeclass(i,ii)/nc
          write(180,'("Average Entry Q Time(min)     
     + = ",f15.3)') timeentry(i,ii)/nc
          write(180,'("Average Stop Time(min)        
     + = ",f15.3)') stoptimeclass(i,ii)/nc
          write(180,'("Average Trip Distance(ml)     
     + = ",f15.3)') disclass(i,ii)/nc
          write(180,*)'----------------------------------'
1200  continue
1201  continue
1     format(f15.3)
2     format(i15)

c 	print *, 'Alex605'
! -- print out statistics for impacted vehicles

       if(inci_num.gt.0) then
          write(666,*) ''
          write(666,*) ''
          write(666,*) ''
          write(666,*) ''
          write(666,*) ''
       write(666,*)'**************************************************'
          write(666,*) ''
	write(666,*) "  The following block is for incident 
     +  impacted vehicle statistics"
          write(666,*) ''
       write(666,*)'**************************************************'

c 	print *, 'Alex606'
					          
      do Mo = 1, inci_num
          write(666,*)' ----------------------------------------------'
          write(666,'(" Incident Location            = ",i15)') MO      
		  do MNO = 1, 2 !1 is non-diverted vehicles
            if(numberIMP(MNO,MO).gt.0) then
		      if(MNO.eq.1) then
                write(666,*)'-Non-Diverted-----------------'
              else
                write(666,*)'-Diverted---------------------'
              endif
	write(666,'("Number of vehicles       = ",i15)') 
     +  numberIMP(MNO,MO)
	write(666,'("Total Trip Times(min)    = ",f15.3)') 
     +  timeIMP(MNO,MO)
        write(666,'("Total Trip Distance(ml)  = ",f15.3)') 
     +  distIMP(MNO,MO)
        write(666,'("Total Stop Time(min)     = ",f15.3)') 
     +  stopIMP(MNO,MO)
        write(666,'("Average Trip Times(min)  = ",f15.3)') 
     + timeIMP(MNO,MO)/numberIMP(MNO,MO)
        write(666,'("Average Stop Time(min)   = ",f15.3)') 
     + stopIMP(MNO,MO)/numberIMP(MNO,MO)
        write(666,'("Average Trip Distance(ml)= ",f15.3)') 
     + distIMP(MNO,MO)/numberIMP(MNO,MO)
		AllNumberIMP = AllNumberIMP + numberIMP(MNO,MO)
		AlltimeIMP = AlltimeIMP + timeIMP(MNO,MO)
		AlldistIMP = AlldistIMP + distIMP(MNO,MO)
		AllstopIMP = AllstopIMP + stopIMP(MNO,MO)
			endif
          enddo
c	 	print *, 'Alex6061'

! -- write sub stat for this incident location
              write(666,*)'-Sub stats--------------------'
              if((numberIMP(1,MO)+numberIMP(2,MO)).gt.0) then 
              write(666,'("Number of vehicles            = ",i15)')   
     + (numberIMP(1,MO)+numberIMP(2,MO))
              write(666,'("Total Trip Times(min)         = ",f15.3)') 
     + (timeIMP(1,MO)+timeIMP(2,MO))
              write(666,'("Total Trip Distance(ml)       = ",f15.3)') 
     + (distIMP(1,MO)+distIMP(2,MO))
              write(666,'("Total Stop Time(min)          = ",f15.3)') 
     + (stopIMP(1,MO)+stopIMP(2,MO))
              write(666,'("Average Trip Times(min)       = ",f15.3)') 
     + (timeIMP(1,MO)+timeIMP(2,MO))/(numberIMP(1,MO)+numberIMP(2,MO))
              write(666,'("Average Stop Time(min)        = ",f15.3)') 
     + (stopIMP(1,MO)+stopIMP(2,MO))/(numberIMP(1,MO)+numberIMP(2,MO))
              write(666,'("Average Trip Distance(ml)     = ",f15.3)') 
     + (distIMP(1,MO)+distIMP(2,MO))/(numberIMP(1,MO)+numberIMP(2,MO))
              write(666,*) 
			  endif
      enddo
c	 	print *, 'Alex6062'

	write(666,*) ''
	write(666,*) ''
	write(666,*) '=========================================='
	write(666,*) 'Overall Incident Impacted Vehicle Statistics  '
	write(666,*) '=========================================='
	write(666,'("Number of vehicles       = ",i15)') AllNumberIMP
        write(666,'("Total Trip Times(min)    = ",f15.3)') AlltimeIMP
        write(666,'("Total Trip Distance(ml)  = ",f15.3)') AlldistIMP
        write(666,'("Total Stop Time(min)     = ",f15.3)') AllstopIMP
	if(AllnumberIMP.gt.0.00001)then
        write(666,'("Average Trip Times(min)  = ",f15.3)') 
     + AlltimeIMP/AllnumberIMP
        write(666,'("Average Stop Time(min)   = ",f15.3)') 
     + AllstopIMP/AllnumberIMP
        write(666,'("Average Trip Distance(ml)= ",f15.3)') 
     + AlldistIMP/AllnumberIMP
	else
        write(666,'("Average Trip Times(min)  = ",f15.3)') 0.0
        write(666,'("Average Stop Time(min)   = ",f15.3)') 0.0
        write(666,'("Average Trip Distance(ml)= ",f15.3)') 0.0
      endif        

	  endif !inci_num.gt.0

! ----------------- Start Work Zone
c 	print *, 'Alex607'
      
	  AlltimeIMP  = 0
	  AlldistIMP  = 0
	  AllstopIMP  = 0
	  AllNumberIMP = 0

       if(WorkZoneNum.gt.0) then
          write(666,*) ''
          write(666,*) ''
          write(666,*) ''
          write(666,*) ''
          write(666,*) ''
        write(666,*)'**************************************************'
          write(666,*) ''
	write(666,*) 
     +"The following block is for Work Zone impacted vehicle statistics"
          write(666,*) ''
	write(666,*)'**************************************************'
				          
      do Mo = 1, WorkZoneNum
          write(666,*)' ----------------------------------------------'
          write(666,'(" Work Zone Location            = ",i15)') MO      
		  do MNO = 1, 2 !1 is non-diverted vehicles
            if(WZnumberIMP(MNO,MO).gt.0) then
		      if(MNO.eq.1) then
                write(666,*)'-Non-Diverted-----------------'
              else
                write(666,*)'-Diverted---------------------'
              endif
              write(666,'("Number of vehicles            = ",i15)')   
     + WZnumberIMP(MNO,MO)
              write(666,'("Total Trip Times(min)         = ",f15.3)') 
     + WZtimeIMP(MNO,MO)
              write(666,'("Total Trip Distance(ml)       = ",f15.3)') 
     + WZdistIMP(MNO,MO)
              write(666,'("Total Stop Time(min)          = ",f15.3)') 
     + WZstopIMP(MNO,MO)
              write(666,'("Average Trip Times(min)       = ",f15.3)') 
     + WZtimeIMP(MNO,MO)/WZnumberIMP(MNO,MO)
              write(666,'("Average Stop Time(min)        = ",f15.3)') 
     + WZstopIMP(MNO,MO)/WZnumberIMP(MNO,MO)
              write(666,'("Average Trip Distance(ml)     = ",f15.3)') 
     + WZdistIMP(MNO,MO)/WZnumberIMP(MNO,MO)
		AllNumberIMP = AllNumberIMP + WZnumberIMP(MNO,MO)
			  AlltimeIMP = AlltimeIMP + WZtimeIMP(MNO,MO)
			  AlldistIMP = AlldistIMP + WZdistIMP(MNO,MO)
			  AllstopIMP = AllstopIMP + WzstopIMP(MNO,MO)
			endif
          enddo
! -- write sub stat for this incident location
              write(666,*)'-Sub stats--------------------'
              if((WZnumberIMP(1,MO)+WZnumberIMP(2,MO)).gt.0) then 
              write(666,'("Number of vehicles            = ",i15)')   
     + (WZnumberIMP(1,MO)+WZnumberIMP(2,MO))
              write(666,'("Total Trip Times(min)         = ",f15.3)') 
     + (WZtimeIMP(1,MO)+WZtimeIMP(2,MO))
              write(666,'("Total Trip Distance(ml)       = ",f15.3)') 
     + (WZdistIMP(1,MO)+WZdistIMP(2,MO))
              write(666,'("Total Stop Time(min)          = ",f15.3)') 
     + (WZstopIMP(1,MO)+WZstopIMP(2,MO))
              write(666,'("Average Trip Times(min)       = ",f15.3)') 
     + (WZtimeIMP(1,MO)+WZtimeIMP(2,MO))/(WZnumberIMP(1,MO)+
     +  WZnumberIMP(2,MO))
              write(666,'("Average Stop Time(min)        = ",f15.3)') 
     + (WZstopIMP(1,MO)+WZstopIMP(2,MO))/(WZnumberIMP(1,MO)+
     + WZnumberIMP(2,MO))
              write(666,'("Average Trip Distance(ml)     = ",f15.3)') 
     + (WZdistIMP(1,MO)+WZdistIMP(2,MO))/(WZnumberIMP(1,MO)+
     + WZnumberIMP(2,MO))
              write(666,*) 
			  endif
      enddo
	          write(666,*) ''
		write(666,*) ''
	write(666,*) '=========================================='
	write(666,*) '  Overall Work Zone Impacted Vehicle Statistics  '
	write(666,*) '=========================================='
        write(666,'("Number of vehicles       = ",i15)') AllNumberIMP
        write(666,'("Total Trip Times(min)    = ",f15.3)') AlltimeIMP
        write(666,'("Total Trip Distance(ml)  = ",f15.3)') AlldistIMP
        write(666,'("Total Stop Time(min)     = ",f15.3)') AllstopIMP
        write(666,'("Average Trip Times(min)  = ",f15.3)') 
     +  AlltimeIMP/AllnumberIMP
        write(666,'("Average Stop Time(min)   = ",f15.3)') 
     + AllstopIMP/AllnumberIMP
	write(666,'("Average Trip Distance(ml)= ",f15.3)') 
     + AlldistIMP/AllnumberIMP
              
	  endif !WorkZoneNum.gt.0

      if(inci_num.gt.0) then
	    deallocate(timeIMP)
	    deallocate(distIMP)
	    deallocate(stopIMP)
	    deallocate(entryIMP)
	    deallocate(totalIMP)
        deallocate(numberIMP)
      endif

      if(WorkZoneNum.gt.0) then
	    deallocate(WZtimeIMP)
	    deallocate(WZdistIMP)
	    deallocate(WZstopIMP)
	    deallocate(WZentryIMP)
	    deallocate(WZtotalIMP)
        deallocate(WZnumberIMP)
      endif
c 	print *, 'Alex608'
!      close (666)      
	return
    	end
