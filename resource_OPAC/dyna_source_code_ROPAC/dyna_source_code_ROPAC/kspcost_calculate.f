	subroutine kspcost_calculate
c --
      	use muc_mod
c --
c -- This subroutie is for the main calculations of the k shortest paths.
c --
c -- This subroutine is called from ksp_main.
c -- This subroutine does not call any other subroutines.
c --
c -- INPUT:
c -- no specific input.
c -- OUTPUT:
c -- k shortest paths.
c --
c --    for improper destinations
	NCountEquality=0
c --
       if(BackPointr(Destin+1)-BackPointr(Destin).eq.0)then
         write (911,*) 'Unacceptable isolated destination',destin
         stop
       endif
       NGenericCounter=0
       iyy=iti_nu
C->DO B.1
C	print *,'AlexUE02521'
	Do 201 While(FirstDeque.NE.INFINITY)
C        Take off the first NODE from the head of Deque
         CurrentNode=FirstDeque
         FirstDeque=StatusInDeque(CurrentNode)
         BackPointrCurrent=BackPointr(CurrentNode)
        NoOfArcsLeaving=BackPointr(CurrentNode+1)-BackPointrCurrent-1
         StatusInDeque(CurrentNode)=-1
 	 NgenericCounter=NgenericCounter+1
C--->DO B.2
C	print *,'AlexUE02522'
         Do 202 I2=0,NoOfArcsLeaving
	   NTransient=BackPointr(CurrentNode)+I2
           Nodee=UNodeOfBackLink(NTransient)
	   Arc=BackPointrCurrent+i2
	   Movements=BackPointr(Nodee+1)-BackPointr(Nodee)
 	   IM=I2+1
	   if(IM.gt.MaxMove)then
		IM=1 
		! Reason 1: Only centriod will satisfy this condition:IM .gt.MaxMove  
		! Reason 2: Labels on the centriod are zero (the same) for all the movements
		! Reason 3: we do not have chances to rescan the centriod.
	   endif
! End of modification
C	print *,'AlexUE02523'
		if(Movements.gt.MaxMove_current)then
		MaxMove_current=Movements;
		endif
	do itime=1,Iti_nu
	UpCounter(ITime)=DequeLabelCounter(CurrentNode,iTime,IM)
        enddo
C	print *,'AlexUE02524'
	IF(StatusInDeque(Nodee).NE.0)THEN
C		print *,'AlexUE025241'
	   do 333 iTime=1,Iti_nu
	     Do 2031 M=1,Movements
C		print *,'AlexUE025242'
c		if(arc.gt.580.or.ITime.gt.1.or.M.gt.12) stop
	      NextPenalty=TTPenalty(arc,ITime,M)
              NPenaltyArrivalIndex=NextPenalty/TimeInterval
	      ArrIndex=ITime+NPenaltyArrivalIndex
	      NextCost=ttmarginal(iTime,arc,M) 
              If(ArrIndex.gt.Iti_nu) ArrIndex=Iti_nu
              NextDistance=TTime(Arc,ArrIndex)
	      NArrivalTime=((NextDistance+NextPenalty)/
     *	      TimeInterval)+ITime+1
	      If(NArrivalTime.gt.Iti_nu) NArrivalTime=Iti_nu
	  IDCounter=DequeLabelCounter(CurrentNode,NArrivalTime,IM)
C		print *,'AlexUE025243'
               Do 203 I3=1,IDCounter
	       KPrevious=DequeLabel2(CurrentNode,NArrivalTime,I3,IM) 
               NewLabel=NextDistance+NextPenalty+
     *	       Label(CurrentNode,NArrivalTime,KPrevious,IM)
C --
c	       if(CurrentNode.gt.206.or.NArrivalTime.gt.1
c    +        .or.KPrevious.gt.3.or.IM.gt.12.or.CurrentNode.lt.1.or.
c     +         NArrivalTime.lt.1.or.KPrevious.lt.1.or.IM.lt.1) stop
C --
        	NewLabelCost=NextCost+
     *  	LabelCost(CurrentNode,NArrivalTime,KPrevious,IM) 
     *  	+cost(Arc,ltype,ioccup)
C--->IF B.2S
               if(FirstGoodLabel(Nodee,ITime,M).GE.KPaths)then
                MaxLabelCost=LabelCost(Nodee,ITime,FirstLabel
     *			(Nodee,ITime,M),M)
	        MaxLabel=Label(Nodee,ITime,FirstLabel
     *			(Nodee,ITime,M),M)
C--->IF B.3S
       		if(NewLabelCost.LT.MaxLabelCost)then
        		Found=.FALSE.
        		Update(M,ITime,I3)=.TRUE.
C---->IF B.3.1S
	 		if(kay.EQ.1)then
         PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),1,M)=
     *		CurrentNode
         PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),2,M)=
     *		KPrevious
         PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),3,M)=
     *		IM
      	 PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),4,M)=
     *		NArrivalTime
C --
c	if(Nodee.gt.206.or.ITime.gt.1.or.FirstLabel(Nodee,ITime,M)
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .FirstLabel(Nodee,ITime,M).lt.1.or.M.lt.1) stop
C --
         LabelCost(Nodee,ITime,FirstLabel(Nodee,ITime,M),M)=
     *	 NewLabelCost
         Label(Nodee,ITime,FirstLabel(Nodee,ITime,M),M)=
     *	 NewLabel
         EmptyLabel=1
	 		else
        SecondLabel=LabelPointer(Nodee,iTime,
     *       FirstLabel(Nodee,ITime,M),M)
        EmptyLabel=FirstLabel(Nodee,Itime,M)
C---->IF B.4S
c	if(Nodee.gt.206.or.ITime.gt.1.or.SecondLabel
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .SecondLabel.lt.1.or.M.lt.1) stop
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.FirstLabel(Nodee,ITime,M)
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .FirstLabel(Nodee,ITime,M).lt.1.or.M.lt.1) stop
c --
        	if(NewLabelCost.Ge.
     *    LabelCost(Nodee,itime,SecondLabel,M))then
         PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),1,M)=
     *		CurrentNode
         PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),2,M)=
     *		KPrevious
         PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),3,M)=
     *		IM
      	 PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),4,M)=
     *		NArrivalTime
         LabelCost(Nodee,ITime,FirstLabel(Nodee,ITime,M),M)=
     *	 NewLabelCost
         Label(Nodee,ITime,FirstLabel(Nodee,ITime,M),M)=
     *	 NewLabel
		else
C----|IF B.4E
C	print *,'AlexUE025244'
          Ktemp=SecondLabel
          Know=LabelPointer(Nodee,ITime,SecondLabel,M)
          Do 7201 While((Know.NE.NIL).AND.(.NOT.Found))
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.Know
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .Know.lt.1.or.M.lt.1) stop
c --
            if(NewLabelCost.GE. 
     *	    LabelCost(Nodee,ITime,Know,M))then
              Found=.TRUE.
            else
              KTemp=Know
              Know=LabelPointer(Nodee,ITime,Ktemp,M)
            endIf
7201      Continue
C	print *,'AlexUE025245'
          FirstLabel(Nodee,ITime,M)=SecondLabel
c	if(Nodee.gt.206.or.ITime.gt.1.or.EmptyLabel
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .EmptyLabel.lt.1.or.M.lt.1) stop
c --
          LabelCost(Nodee,ITime,EmptyLabel,M)=NewLabelCost
          Label(Nodee,ITime,EmptyLabel,M)=NewLabel
          LabelPointer(Nodee,ITime,EmptyLabel,M)=Know
          LabelPointer(Nodee,ITime,Ktemp,M)=EmptyLabel
          PathPointer(Nodee,ITime,EmptyLabel,1,M)=CurrentNode
          PathPointer(Nodee,ITime,EmptyLabel,2,M)=KPrevious
          PathPointer(Nodee,ITime,EmptyLabel,3,M)=IM
          PathPointer(Nodee,ITime,EmptyLabel,4,M)=NArrivalTime
        	endif
C----<IF B.4F
			endif
C----<IF B.3.1F
C	print *,'AlexUE02525'
	 I=1
	 Found=.False.
	 Do 7202 While((.NOT.(Found)).AND.
     *     (I.LE.DequeLabelCounter(Nodee,ITime,M))) 
	   If(DequeLabel2(Nodee,ITime,I,M).EQ.EmptyLabel)Then
c --
c	if(Nodee.gt.206.or.itime.gt.1.or.I.gt.3.or.m.gt.12) stop
c --
             DequeLabel1(Nodee,iTime,I,M)=NewLabel
	     DequeLabel1Cost(Nodee,iTime,I,M)=NewLabelCost
	     Found=.True.
	   Else
	     I=I+1
	   EndIf
7202	 Continue
C	print *,'AlexUE025251'
	If(.NOT.(Found))Then
	  DequeLabelCounter(Nodee,ITime,M)=
     *		DequeLabelCounter(Nodee,ITime,M)+1
c --
c	if(Nodee.gt.206.or.itime.gt.1.or.DequeLabelCounter
c     *		(Nodee,iTime,M).gt.3.or.m.gt.12) stop

          DequeLabel1(Nodee,ITime,DequeLabelCounter
     *		(Nodee,iTime,M),M)=NewLabel
	    DequeLabel1Cost(Nodee,ITime,DequeLabelCounter
     *		(Nodee,iTime,M),M)=NewLabelCost
          DequeLabel2(Nodee,ITime,DequeLabelCounter
     *		(Nodee,ITime,M),M)=EmptyLabel
	EndIf
!	ENDIF
!C----<IF B.3.1F
      		else
C---|IF B.3E
C	print *,'AlexUE025252'
		Update(M,ITime,I3)=.False.
	        endif
C---<IF B.3F
            else
C---|IF B.2E
C	print *,'AlexUE025253'
       Update(M,ITime,I3)=.TRUE.
       Found=.FALSE.
       FirstGoodLabel(Nodee,ITime,M)=FirstGoodLabel(Nodee,ITime,M)+1
       Label(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),M)=NewLabel
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.FirstGoodLabel(Nodee,ITime,M)
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .FirstGoodLabel(Nodee,ITime,M).lt.1.or.M.lt.1) stop
c --
       LabelCost(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),M)=
     * NewLabelCost
C------>IF B.5S
       If(NewLabelCost.Ge.LabelCost(Nodee,ITime,
     *		FirstLabel(Nodee,ITime,M),M))Then
       LabelPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITIme,M),M)=
     *		FirstLabel(Nodee,ITime,M)
       FirstLabel(Nodee,ITime,M)=FirstGoodLabel(Nodee,ITime,M)
       PathPointer(Nodee,ITime,FirstGoodLabel(Nodee,iTime,M),1,M)=
     *		CurrentNode
       PathPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),2,M)=
     *		KPrevious
       PathPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),3,M)=
     *		IM
       PathPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),4,M)=
     *  	NArrivalTime		
       Else
C------|IF B.5S
       Know=LabelPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),M)
       Ktemp=FirstLabel(Nodee,ITime,M)
C	print *,'AlexUE025254'
        Do 8201 While((Know.NE.NIL).AND.(.NOT.Found))
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.Know
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .Know.lt.1.or.M.lt.1) stop
c --
          If(NewLabelCost.Ge. 
     *	LabelCost(Nodee,ITime,Know,M))Then
            Found=.TRUE.
          Else
            Ktemp=Know
            Know=LabelPointer(Nodee,ITime,Ktemp,M)
          EndIf
8201     Continue
C	print *,'AlexUE025255'
       LabelPointer(Nodee,ITime,FirstGoodLabel
     *		(Nodee,ITime,M),M)=Know
       LabelPointer(Nodee,ITime,Ktemp,M)=
     +   FirstGoodLabel(Nodee,ITime,M)
       PathPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),1,M)=
     *		CurrentNode
       PathPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),2,M)=
     *		KPrevious
       PathPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),3,M)=
     *		IM
       PathPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),4,M)=
     *		NArrivalTime
        Endif
C-----<IF B.5F
C	print *,'AlexUE025256'
       DequeLabelCounter(Nodee,ITime,M)=
     *		DequeLabelCounter(Nodee,ITime,M)+1
c --
c	if(Nodee.gt.206.or.itime.gt.1.or.
c     +  DequeLabelCounter(Nodee,ITIme,M).gt.3.or.m.gt.12) stop
c --
       DequeLabel1(Nodee,ITime,DequeLabelCounter(Nodee,ITIme,M),M)
     *		=NewLabel
	   DequeLabel1Cost(Nodee,ITime,
     *   DequeLabelCounter(Nodee,ITIme,M),M)=NewLabelCost
         DequeLabel2(Nodee,iTime,DequeLabelCounter(Nodee,ITime,M),M)
     *   =FirstGoodLabel(Nodee,ITime,M)	
         EndIf
C---<IF B.2F
C	print *,'AlexUE025257'
203      Continue
C	print *,'AlexUE025258'
2031	  Continue
C	print *,'AlexUE02526'
c --
C  This part updates the Label of The Next Node without
c  the Intermovements.- Real Label
	M=Movements+1
! We do not load entry queue on connectors, but on generation links
!	  NextDistance=TTpenalty(arc,ITime,M)
      	NextDistance=0
	NArrivalNoPen=NextDistance/TimeInterval+ITime+1
! We do not load entry queue on connectors, but on generation links
!	  NextCost=ttmarginal(iTime,arc,M)
c --
	  If(NArrivalNoPen.gt.Iti_nu) NArrivalNoPen=Iti_nu
	  IDCounter=DequeLabelCounter(CurrentNode,NArrivalTime,IM)
	  Do 2132 I3=1,IDCounter
	  KPrevious=DequeLabel2(CurrentNode,NarrivalTime,I3,IM)
          NewLabel=Label(CurrentNode,NArrivalNoPen,KPrevious,IM)+
     *	       NextDistance
	    NewLabelCost=LabelCost
     *        (CurrentNode,NArrivalNoPen,KPrevious,IM)
     *	      + NextCost
     *          + cost(Arc,ltype,ioccup)
C--->IF B.2rS
          If(FirstGoodLabel(Nodee,iTime,M).GE.KPaths)Then
          MaxLabel=Label(Nodee,ITime,FirstLabel(Nodee,ITime,M),M)
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.FirstLabel(Nodee,ITime,M)
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .FirstLabel(Nodee,ITime,M).lt.1.or.M.lt.1) stop
c --
	  MaxLabelCost=
     *    LabelCost(Nodee,ITime,FirstLabel(Nodee,ITime,M),M)
C--->IF B.3rS
             If(NewLabelCost.LT.MaxLabelCost)Then
        Found=.FALSE.
C--->IF B.3.1rS	
		If(Kay.EQ.1)then
         PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),1,M)=
     *		CurrentNode
         PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),2,M)=
     *		KPrevious
         PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),3,M)=
     *		IM
         PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),4,M)=
     *		NArrivalNoPen
         Label(Nodee,ITime,FirstLabel(Nodee,ITime,M),M)=NewLabel
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.FirstLabel(Nodee,ITime,M)
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .FirstLabel(Nodee,ITime,M).lt.1.or.M.lt.1) stop
c --
         LabelCost(Nodee,ITime,FirstLabel(Nodee,ITime,M),M)=
     *   NewLabelCost  
C---->IF B.3.1rE       
	else
        SecondLabel=LabelPointer(Nodee,ITime,FirstLabel
     *	   (Nodee,iTime,M),M)
C---->IF B.4rS
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.SecondLabel
c    +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .SecondLabel.lt.1.or.M.lt.1) stop
c --    
        If(NewLabelCost.Ge.
     *    LabelCost(Nodee,ITime,SecondLabel,M))Then
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.FirstLabel(Nodee,ITime,M)
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .FirstLabel(Nodee,ITime,M).lt.1.or.M.lt.1) stop
c --
        PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),1,M)=
     *		CurrentNode
        PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),2,M)=
     *		KPrevious
        PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),3,M)=
     *		IM
        PathPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),4,M)=
     *		NArrivalNoPen
        Label(Nodee,ITime,FirstLabel(Nodee,ITime,M),M)=NewLabel
        LabelCost(Nodee,ITime,FirstLabel(Nodee,ITime,M),M)=
     *   NewLabelCost  
        Else
C----|IF B.4rE
        EmptyLabel=FirstLabel(Nodee,ITime,M)
        Ktemp=SecondLabel
        Know=LabelPointer(Nodee,ITime,SecondLabel,M)
        Do 7211 While((Know.NE.NIL).AND.(.NOT.Found))
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.Know
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .Know.lt.1.or.M.lt.1) stop
c --
          If (NewLabelCost.GE. 
     *    	LabelCost(Nodee,iTime,Know,M))Then
            Found=.TRUE.
          Else
            KTemp=Know
            Know=LabelPointer(Nodee,iTime,Ktemp,M)
          EndIf
7211     Continue
         FirstLabel(Nodee,iTime,M)=SecondLabel
         Label(Nodee,iTime,EmptyLabel,M)=NewLabel
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.EmptyLabel
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .EmptyLabel.lt.1.or.M.lt.1) stop
c --
         LabelCost(Nodee,iTime,EmptyLabel,M)=NewLabelCost  
         LabelPointer(Nodee,iTime,EmptyLabel,M)=Know
         LabelPointer(Nodee,iTime,Ktemp,M)=EmptyLabel
         PathPointer(Nodee,iTime,EmptyLabel,1,M)=CurrentNode
	 PathPointer(Nodee,iTime,EmptyLabel,2,M)=KPrevious
 	 PathPointer(Nodee,iTime,EmptyLabel,3,M)=IM
 	 PathPointer(Nodee,iTime,EmptyLabel,4,M)=NArrivalNoPen
         EndIf
C----<IF B.4rF
	   Endif	
C----<IF B.3.1rF
         EndIf
C----<IF B.3rF
C	print *,'AlexUE02526-1'
            Else
        Found=.FALSE.
       FirstGoodLabel(Nodee,Itime,M)=FirstGoodLabel(Nodee,ITime,M)+1
        Label(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),M)=NewLabel
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.FirstGoodLabel(Nodee,ITime,M)
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .FirstGoodLabel(Nodee,ITime,M).lt.1.or.M.lt.1) stop
c --
	  LabelCost(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),M)=
     *  NewLabelCost
        PathPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),1,M)=
     *		CurrentNode
        PathPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),2,M)=
     *		KPrevious
        PathPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),3,M)=
     *		IM
        PathPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),4,M)=
     *		NArrivalNoPen
C------>IF B.5rS
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.FirstGoodLabel(Nodee,ITime,M)
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .FirstGoodLabel(Nodee,ITime,M).lt.1.or.M.lt.1) stop
c --
       If(NewLabelCost.Ge.LabelCost(Nodee,itime,FirstLabel
     * 		(Nodee,ITime,M),M))Then
       LabelPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),M)=
     *		FirstLabel(Nodee,ITime,M)
        FirstLabel(Nodee,ITime,M)=FirstGoodLabel(Nodee,ITime,M)
       Else
C------|IF B.5rE
       Know=LabelPointer(Nodee,ITime,FirstLabel(Nodee,ITime,M),M)
        Ktemp=FirstLabel(Nodee,ITime,M)
        Do 8211 While((Know.NE.NIL).AND.(.NOT.Found))
c --
c	if(Nodee.gt.206.or.ITime.gt.1.or.Know
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.ITime.lt.1.or
c     +  .Know.lt.1.or.M.lt.1) stop
c --
          If(NewLabelCost.Ge.
     *	 Labelcost(Nodee,ITime,Know,M))Then
            Found=.TRUE.
          Else
            Ktemp=Know
            Know=LabelPointer(Nodee,ITime,Ktemp,M)
          EndIf
8211     Continue
         LabelPointer(Nodee,ITime,FirstGoodLabel(Nodee,ITime,M),M)
     *		=Know
         LabelPointer(Nodee,ITime,Ktemp,M)=FirstGoodLabel
     *		(Nodee,ITime,M)
        Endif
C-----<IF B.5rF
            EndIf
C---<IF B.2F
C	print *,'AlexUE02526-2'
2132	continue
c  To the next time interval at Node.
333	continue
c  I have moved this out of the loop because we may need these counters
c  multiple times as we discover the NArrival Times
C	print *,'AlexUE02527'
        Do 2222 ITime=1,Iti_nu
	    DequeLabelCounter(CurrentNode,ITime,IM)=0
2222	continue
C	print *,'AlexUE02528'
c---------------------------------------------------------------------
c  If Node has not been scanned previously:
       ELSE
c	print *,'AlexUE02526-3'
C---<IF B.1E
	Do 334 NTime=1,Iti_nu
	  DequeLabelCounter(CurrentNode,NTime,IM)=0
c	print *,'AlexUE02526-31'
         Do 9031 M=1,Movements
c		if(arc.gt.580.or.NTime.gt.1.or.M.gt.12) stop
	  NextPenalty=TTPenalty(Arc,NTime,M)
          NPenaltyArrivalIndex=NextPenalty/TimeInterval
	  ArrIndex=Ntime+NPenaltyArrivalIndex
	  If(ArrIndex.gt.Iti_nu)ArrIndex=Iti_nu
          NextDistance=TTime(Arc,ArrIndex)
	  NArrivalTime=((NextPenalty+NextDistance)/
     *		TimeInterval)+NTime+1
	  NextCost=ttmarginal(NTime,arc,M)
	  If(NArrivalTime .gt. Iti_nu) NArrivalTime=Iti_nu
          FirstGoodLabel(Nodee,NTime,M)=FirstGoodLabel
     *		(CurrentNode,NTime,IM)
         FirstLabel(Nodee,NTime,M)=FirstLabel(CurrentNode,NTime,IM)
      DequeLabelCounter(Nodee,NTime,M)=FirstGoodLabel(Nodee,NTime,M)
c --
c	print *,'AlexUE02526-32'
	 Do 9199 IK=1,FirstGoodLabel(CurrentNode,NTime,IM)
	   Label(Nodee,NTime,IK,M)=NextDistance+NextPenalty+
     *	   Label(CurrentNode,NArrivalTime,IK,IM)
c --
c	print *,'AlexUE02526-321'
c	if(Nodee.gt.206.or.NTime.gt.1.or.IK
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.NTime.lt.1.or
c     +  .IK.lt.1.or.M.lt.1) stop
c --
c	print *,'AlexUE02526-322'
c -- Alex-problem: large dimentions
c	if(CurrentNode.gt.206.or.NArrivalTime.gt.1.or.IK
c     +  .gt.3.or.IM.gt.12.or.CurrentNode.lt.1.or.NArrivalTime.lt.1.or
c     +  .IK.lt.1.or.IM.lt.1) stop
c --
c	print *, CurrentNode,NArrivalTime,IK
c     +  ,IM,CurrentNode,NArrivalTime,IK,IM

c	print *,'AlexUE02526-323'
	   LabelCost(Nodee,NTime,IK,M)=
     *	   LabelCost(CurrentNode,NArrivalTime,IK,IM)
     *      +NextCost+cost(Arc,ltype,ioccup)
           LabelPointer(Nodee,NTime,IK,M)=LabelPointer
     *		(CurrentNode,NTime,IK,IM)
           PathPointer(Nodee,NTime,IK,1,M)=CurrentNode
           PathPointer(Nodee,NTime,IK,2,M)=IK
           PathPointer(Nodee,NTime,IK,3,M)=IM
           PathPointer(Nodee,NTime,IK,4,M)=NArrivalTime
c       if(Nodee.gt.206.or.Ntime.gt.1.or.IK.gt.3.or.m.gt.12) stop
          DequeLabel1(Nodee,NTime,IK,M)=Label(Nodee,NTime,IK,M)
	  DequeLabel1Cost(Nodee,NTime,IK,M)=
     *   LabelCost(Nodee,NTime,IK,M)
           DequeLabel2(Nodee,NTime,IK,M)=IK
9199     Continue
         Update(M,NTime,1)=.True.

9031    Continue
c	print *,'AlexUE02529'
	 M=Movements+1
! We do not load entry queue on connectors, but on generation links
!	 NextDistance=TTpenalty(arc,NTime,M)
	 NextDistance=0
	 NArrivalNoPen=NextDistance/TimeInterval+NTime+1
! We do not load entry queue on connectors, but on generation links
!	 NextCost=ttmarginal(Ntime,arc,M)
	 NextCost=0
	 If(NArrivalNoPen.gt.Iti_nu) NArrivalNoPen=Iti_nu
         FirstGoodLabel(Nodee,NTime,M)=FirstGoodLabel
     *		(CurrentNode,NTime,IM)
       FirstLabel(Nodee,NTime,M)=FirstLabel(CurrentNode,NTime,IM)
	 Do 9299 IO=1,FirstGoodLabel(CurrentNode,NTime,IM)
	Label(Nodee,NTime,IO,M)=Label(CurrentNode,
     *	NArrivalNoPen,IO,IM)+NextDistance
c --
c	if(Nodee.gt.206.or.NArrivalNoPen.gt.1.or.IO
c     +  .gt.3.or.M.gt.12.or.Nodee.lt.1.or.NArrivalNoPen.lt.1.or
c     +  .IO.lt.1.or.M.lt.1) stop
c --
c	if(CurrentNode.gt.206.or.NTime.gt.1.or.IO
c     +  .gt.3.or.IM.gt.12.or.CurrentNode.lt.1.or.NTime.lt.1.or
c     +  .IO.lt.1.or.IM.lt.1) stop
c --
	LabelCost(Nodee,NTime,IO,M)=LabelCost(CurrentNode,
     *	NArrivalNoPen,IO,IM)+NextCost+cost(Arc,ltype,ioccup)
        LabelPointer(Nodee,NTime,IO,M)=
     *	LabelPointer(CurrentNode,NTime,IO,IM)
           PathPointer(Nodee,NTime,IO,1,M)=CurrentNode
           PathPointer(Nodee,NTime,IO,2,M)=IO
           PathPointer(Nodee,NTime,IO,3,M)=IM
           PathPointer(Nodee,NTime,IO,4,M)=NArrivalNoPen
9299     Continue

334	continue

       ENDIF
C--->IF B.1F
c-Comment B.2: Check the Update Status and Insert the Node in the Deque
c	print *,'AlexUE025210'
	 UpdateCombined=.FALSE.
	Do 2033 ITime=1,Iti_nu
	 IDCounter=DequeLabelCounter(CurrentNode,ITime,IM)
	 Do 2032 I3=1,UpCounter(ITime)
	  Do 2032 M=1,Movements
	    If (Update(M,ITime,I3))Then
	      UpdateCombined=.TRUE.
	      Update(M,ITime,I3)=.False.
	    EndIf
2032	  Continue
2033    continue
c --
c	print *,'AlexUE025211'
          If(UpdateCombined)Then 
        If(StatusInDeque(Nodee).EQ.0)Then
           If(FirstDeque.NE.INFINITY)Then
              StatusInDeque(LastDeque)=Nodee
              StatusInDeque(Nodee)=INFINITY
              LastDeque=Nodee
           Else
              StatusInDeque(Nodee)=FirstDeque
              FirstDeque=Nodee
              LastDeque=Nodee
           EndIf
        Else
           If(StatusInDeque(Nodee).EQ.-1)Then
              If(FirstDeque.EQ.INFINITY) LastDeque=Nodee
              StatusInDeque(Nodee)=FirstDeque
              FirstDeque=Nodee
           EndIf
        EndIf
       EndIf
202     Continue
C--<DO B.2
201   Continue
C-<DO B.1
901	Format (I10)
      return
      end
